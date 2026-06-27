---
uuid: a2f46b22ca554d12a226159b5f6c8dbb
title: Training success writes Model QRO
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-training-entrypoint
source: goal-gap
source_ref: GOAL §1/§7/§8/§14/§15/§16 training/model entrypoint writes QRO / Research Graph
depends_on: [10b2399615a8495c9e2c569919a92a25]
completed_at: 2026-06-27
---

# Training success writes Model QRO

## Scope [必填]
把训练台成功产出模型版本的路径接入 Research Graph。`TrainingService` 在 job 真正 `succeeded` 且 `model_version` 已登记后，调用 app-level recorder 写 `Model` QRO，并把 `qro_id` / `research_graph_command_id` 持久化回 `TrainingJob`。

## 上下文 / 动机 [按需]
此前训练成功会写 ModelRegistry version、ModelPassport 和 ValidationDossier refs，但不会产生 QRO/Research Graph command。GOAL §15 要求模型治理对象进入统一 QRO/Graph；本卡先闭合“训练成功 → Model QRO”这条 runtime seam，不把 queued job、失败 job 或无模型产物的自由代码 job 伪装成模型 QRO。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/training/store.py` | `TrainingJob` 增加 `qro_id` / `research_graph_command_id`，旧 JSONL 默认值兼容 |
| `app/backend/app/training/service.py` | `TrainingService` 增加 `result_recorder`；成功产出 `model_version` 后调用 recorder |
| `app/backend/app/main.py` | 新增 `_record_training_job_qro`，TrainingService 初始化接入 recorder，QRO audit allowlist 增加安全 training refs/hash |
| `app/backend/tests/test_training_api.py` | 覆盖训练成功写 Model QRO，QRO/audit 不泄露 metrics 明细或 artifact path |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. queued job 不能写 QRO；必须等训练线程真正 succeeded 且 model version 已登记。
2. 无模型版本的成功 job 不写 Model QRO，不能把自由代码/无产物任务伪装成模型资产。
3. QRO 只保存 job/model/version/passport/dossier/run refs 与 request/metrics hash，不保存 metrics 明细、artifact_dir、artifact_path 或模型二进制路径。
4. 轮询 `GET /api/training/jobs/{job_id}` 必须能看到成功 job 的 QRO refs。

## 红线 [按需]
- 不允许把训练成功说成 promotion approval、live serving readiness 或执行许可。
- 不允许把 raw metrics 或 artifact path 放进 QRO contract/audit。
- 不允许为了写 Graph 改弱 ModelPassport / ValidationDossier 现有门。

## 非目标 [按需]
不实现 Model Registry promotion QRO，不实现 runtime serving，不实现完整 compiler/codegen 策略生成，不实现 sandbox artifact inspection process，不实现 live model promotion 或所有训练/模型相关 API 入口。

## 验收一句话 [必填]
结构化训练 job 真正成功并登记 model version 后，会写 `Model` QRO；job 轮询结果返回 QRO refs，Graph audit 只暴露 refs/hash，不暴露 metrics 明细或 artifact path。

## 完成记录（2026-06-27）
- `TrainingJob` schema 增加 `qro_id` / `research_graph_command_id`。
- `TrainingService.result_recorder` 在成功产出 `model_version` 后调用；无模型版本成功 job 不写 QRO。
- `_record_training_job_qro` 写 `QROType.MODEL`，`EntrySource.API`，只保存 request hash、metrics hash、ModelVersion/ModelPassport/ValidationDossier/training run refs。
- 本地验证：
  - `python -m pytest app/backend/tests/test_training_api.py::test_training_success_records_model_qro_without_metrics_or_artifact_payload -q` -> 1 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_training_api.py app/backend/tests/test_training_service.py app/backend/tests/test_model_governance.py app/backend/tests/test_model_desk_m2.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_entrypoint_gate_coverage.py -q` -> 99 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_training_api.py app/backend/tests/test_training_service.py app/backend/tests/test_model_governance.py app/backend/tests/test_model_desk_m2.py app/backend/tests/test_monitor_production.py app/backend/tests/test_monitor_closure.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 135 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️；DAG 147 卡。
