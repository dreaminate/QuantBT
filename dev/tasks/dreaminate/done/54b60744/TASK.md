---
uuid: 54b60744f2564ecc8fd9ef8733b26810
title: Training success compiles Model QRO into entrypoint coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-training-entrypoint
source: goal-gap
source_ref: GOAL §1/§7/§8/§14/§15 training/model QRO -> Graph -> Compiler -> Evidence coverage
depends_on: [a2f46b22ca554d12a226159b5f6c8dbb, 173405ef47f942ba9929a4c356483d07, 9d175460a9f24650964a250304c44d83, d6bbdb2e3d0a49389008d0c48aa31f2e]
completed_at: 2026-06-27
---

# Training success compiles Model QRO into entrypoint coverage

## Scope [必填]
把训练成功产模型版本的 Model QRO 继续接到 Governed Compiler 和 GOAL entrypoint coverage。`TrainingService.result_recorder` 成功写 `Model` QRO 后，必须同步生成 compiler IR/pass，并让 `GET /api/training/jobs/{job_id}` 暴露 compiler/coverage refs。

## 上下文 / 动机 [按需]
`a2f46b22` 已让训练成功路径写 Model QRO/Research Graph command，但 GOAL §1/§7/§8/§15 要求训练入口也进入 QRO -> Graph -> Compiler -> Evidence/Validation 链。此前训练成功只到 QRO/Graph，仍可依赖人工 compile，不足以证明训练入口本身接线。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/training/store.py` | `TrainingJob` 增加 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref` |
| `app/backend/app/training/service.py` | `result_recorder` 返回 compiler/coverage refs 后写回 job snapshot |
| `app/backend/app/main.py` | `_record_training_job_qro` 写 Graph 后调用 `_compile_training_job_qro`，复用 compiler/coverage validator |
| `app/backend/tests/test_training_api.py` | 覆盖训练成功返回 compiler/coverage refs、refs 绑定同一 QRO/command、不泄露 metrics/artifact path |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档训练入口 compiler coverage 和剩余边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 训练成功 job 轮询结果必须返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。
2. compiler IR/pass/coverage 必须绑定同一 `Model` QRO 和 Research Graph command。
3. compiler refs 必须引用 `model_passport_ref`、`validation_dossier_ref` 和 `training.job:service` permission。
4. QRO、Graph audit、compiler IR/pass 和 coverage 都不能复制 metrics 明细、artifact_dir、artifact_path 或模型二进制路径。

## 红线 [按需]
- 不允许把训练成功 compiler coverage 说成模型晋级、live serving 或执行权限。
- 不允许把 artifact path、模型文件、metrics 明细塞进 compiler/coverage。
- 不允许绕过 ModelPassport / ValidationDossier 成功登记。

## 非目标 [按需]
不实现完整 compiler strategy/model codegen、runtime auto-promotion、live model serving、container sandbox、remote artifact store、CI 或线上训练集群证明。

## 验收一句话 [必填]
训练成功产模型版本路径现在会从 Model QRO 自动生成 governed compiler IR/pass 和 API entrypoint coverage；API 轮询可见 refs，但不泄露 raw metrics 或 artifact paths。

## 完成记录（2026-06-27）
- `TrainingJob` snapshot 新增 compiler/coverage refs，`TrainingService` 在 recorder 返回后写回。
- `_record_training_job_qro` 写 Graph 后调用 `_compile_training_job_qro`，绑定 ModelVersion、ModelPassport、ValidationDossier、request hash、metrics hash、permission/env/run-plan refs。
- 本地验证：
  - `pytest app/backend/tests/test_training_api.py -q` -> 10 passed / 2 warnings。
