---
uuid: 0e5c2a9db4f94c9fb7d1a6e2c83f5170
title: Model artifact sandbox inspection process
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-model-governance
source: goal-gap
source_ref: GOAL §15 Artifact safety sandboxed load / inspect
depends_on: [f6d7a3b8a1d24a79b5970c5e8a3f0b16]
completed_at: 2026-06-27
---

# Model artifact sandbox inspection process

## Scope [必填]
把 GOAL §15 的 `sandboxed load / inspect` 从 passport 字段升级为可执行、可验证、可审计的本地 inspection 流程：训练产物生成后跑隔离子进程 inspection，写 `artifact_inspection.json`，`.pkl/.joblib` loader 必须同时验证 validation dossier 与 inspection 记录，Model Governance registry/API 记录 `ModelArtifactInspectionRecord`。

## 上下文 / 动机 [按需]
之前模型产物已有 `validation_dossier.json` 和 hash guard，但 `.pkl/.joblib` 最终仍由主进程 `pickle.load`。本卡补上独立 inspection 产物与 governance 记录层；对 pickle/joblib 只做 metadata/hash inspection，不在 inspection 阶段反序列化对象。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/training/artifact_inspection_worker.py` | 新增子进程 worker：hash/file 检查、pickle/joblib metadata-only scan、safe_tensors header、torch weights_only dry load |
| `app/backend/app/training/artifact_inspection.py` | 新增主进程 wrapper，调用 worker 并返回结构化 inspection |
| `app/backend/app/training/service.py` | 训练成功登记 model version 前跑 inspection，写 `artifact_inspection.json`、dossier ref、passport sandbox ref，并记录 governance artifact inspection |
| `app/backend/app/training/lib.py` | `.pkl/.joblib` load 前必须同时验证 `validation_dossier.json` 与 `artifact_inspection.json` |
| `app/backend/app/research_os/model_governance.py` | 新增 `ModelArtifactInspectionRecord`、append-only replay、passport/artifact/hash/inspection_ref gate |
| `app/backend/app/main.py` | 新增 artifact inspection API 和 model governance summary 字段 |
| `app/backend/tests/test_model_governance.py` | 覆盖 artifact inspection registry/API/replay/hash mismatch |
| `app/backend/tests/test_training_service.py` | 覆盖训练产物 inspection 文件和 loader 缺 inspection fail-closed |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 没有 `artifact_inspection.json` 的 `.pkl/.joblib` 不允许加载。
2. `artifact_inspection.json` 的 path/hash/ref 必须和 `validation_dossier.json`、实际 artifact 一致。
3. `.pkl/.joblib` inspection 必须是 `metadata_only_no_deserialize`，且 `deserialize_executed=false`。
4. Governance artifact inspection 必须绑定已登记 passport 和 passport artifact hash。
5. Passport 声称 `sandboxed_load_inspect=True` 时，artifact 必须带 `sandbox_inspection_ref`。

## 红线 [按需]
- 不允许在 inspection 阶段反序列化 pickle/joblib。
- 不允许把 metadata-only inspection 说成模型执行安全证明。
- 不允许接受 hash 不匹配或未绑定 passport 的 inspection record。
- 不允许把本地子进程 inspection 说成 remote artifact store、生产 sandbox 或 live serving。

## 非目标 [按需]
不实现 remote artifact store，不实现 runtime serving，不实现 runtime auto-promotion，不实现 live model serving，不实现容器级/内核级 sandbox，不实现外部监控系统接线。

## 验收一句话 [必填]
训练成功产物会生成隔离子进程 inspection 记录，pickle/joblib loader 必须验证 dossier + inspection 双绑定；Model Governance registry/API 可 append-only 记录 artifact inspection，坏 hash/坏 ref/缺 inspection 会 fail-closed。

## 完成记录（2026-06-27）
- 新增本地子进程 artifact inspection worker/wrapper；pickle/joblib 只做 metadata-only scan，不反序列化。
- TrainingService 写 `artifact_inspection.json`，将 `artifact_inspection_ref` 写入 validation dossier 和 ModelPassport，并记录 `ModelArtifactInspectionRecord`。
- `load_model` 对 `.pkl/.joblib` 新增 `artifact_inspection.json` 强制校验。
- Model Governance registry/API/summary 新增 artifact inspection record。
- 本地验证：
  - `python -m pytest app/backend/tests/test_model_governance.py -q` -> 28 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_training_service.py -q` -> 15 passed。
  - `python -m pytest app/backend/tests/test_training_api.py app/backend/tests/test_training_service.py app/backend/tests/test_model_governance.py app/backend/tests/test_model_desk_m2.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 136 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️；DAG 151 卡。
