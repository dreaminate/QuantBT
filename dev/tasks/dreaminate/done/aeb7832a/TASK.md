---
uuid: aeb7832ae0f84d0198ec5e2f4762baf0
title: Model Governance runtime records compile into entrypoint coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-model-governance-entrypoint-coverage
source: goal-gap
source_ref: GOAL §1/§8/§9/§14/§15 Model Governance monitoring/recertification/artifact/serving QRO -> Graph -> Compiler -> Coverage
depends_on: [ee8040b930444d8f88b014dd4e62d91a, 4056a87fd1064539b9272c679f017990, 9d175460a9f24650964a250304c44d83, 173405ef47f942ba9929a4c356483d07]
completed_at: 2026-06-27
---

# Model Governance runtime records compile into entrypoint coverage

## Scope [必填]
把 Model Governance 的 monitoring profile、recertification record、artifact inspection 和 model serving invocation 成功路径接到 QRO、Research Graph command、Governed Compiler IR/pass 和 GOAL entrypoint coverage。保留 registry/summary 语义，不改模型训练、promotion gate、artifact loader、signal contract 注册或真实外部 serving 环境。

## 上下文 / 动机 [按需]
`ee8040b9` 已让 Model Registry promotion pending/rejected/approved 写 Model QRO 并自动生成 compiler/coverage refs。剩余 §15 同类缺口是 monitoring、recertification、artifact inspection 和 serving invocation 仍只停在 registry 或 prediction response，没有形成统一 QRO -> Graph -> Compiler -> Coverage 证据链。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `_record_model_monitoring_profile_qro`、`_record_model_recertification_qro`、`_record_model_artifact_inspection_qro`、`_record_model_serving_invocation_qro`；三个 model_governance POST 和 `/api/models/{model_id}/versions/{version}/predict` 成功后返回 QRO/Graph/compiler/coverage refs |
| `app/backend/tests/test_model_governance.py` | 测试 helper 隔离 ResearchGraph/Compiler/Coverage store；断言四条成功路径的 entrypoint coverage、permission refs、QRO type 和 raw payload 不泄漏；拒绝分支不写 partial records |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本轮 Model Governance compiler coverage 和剩余边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `monitoring_profiles` 成功后必须返回 Model QRO、Research Graph command、compiler IR/pass 和 coverage refs，coverage entrypoint 是 `api:research_os.model_governance.monitoring_profiles`。
2. `recertification_records` 成功后必须返回 ValidationDossier QRO 和 coverage refs；未声明 trigger 的 422 不写 registry/Graph/Compiler/Coverage partial records。
3. `artifact_inspections` 成功后必须返回 ValidationDossier QRO 和 coverage refs；compiler audit 只保存 refs/hash/count，不保存 raw loader limitation text 或 artifact path。
4. model `predict` 成功后必须返回 Forecast QRO 和 `api:models.predict` coverage；compiler audit 不保存 feature rows、prediction values 或 local artifact path。

## 红线 [按需]
- 不把 monitoring profile 说成 recertification、promotion approval、live serving proof 或交易权限。
- 不把 artifact inspection 说成 artifact 已安全执行或模型已可上线。
- 不把 serving invocation 说成 portfolio construction、order intent、order submission 或 live trading permission。
- 不把本地全套 tests 说成 CI、线上或用户验收。

## 非目标 [按需]
不实现完整 compiler codegen、模型训练新算法、runtime auto-promotion、remote artifact sandbox、真实外部 serving、真实 broker/venue order、CI、线上或用户验收。

## 验收一句话 [必填]
Model Governance 的 monitoring profile、recertification、artifact inspection 和 serving invocation 成功路径现在都会生成 refs-only QRO、Research Graph command、governed compiler IR/pass 与 GOAL entrypoint coverage；失败路径不写 partial records，raw evidence/rows/predictions/artifact path 不进入 Graph/Compiler。

## 完成记录（2026-06-27）
- 新增四个 Model Governance QRO producer，分别覆盖 monitoring profile、recertification、artifact inspection 和 serving invocation。
- 三个 `/api/research-os/model_governance/*` POST 和 `/api/models/{model_id}/versions/{version}/predict` 成功 response 新增 `qro_id`、`research_graph_command_id`、`compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `pytest app/backend/tests/test_model_governance.py -q` -> 31 passed / 2 warnings。
  - `pytest app/backend/tests/test_model_governance.py app/backend/tests/test_training_api.py app/backend/tests/test_training_service.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_research_os_spine.py -q` -> 102 passed / 2 warnings。
  - `pytest app/backend/tests -q` -> 1804 passed / 13 skipped / 283 warnings.
