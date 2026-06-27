---
uuid: fb378e4256ec41ba9a9de137382a8fdc
title: TrainingRun produces governed ModelPassport
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-model-governance
source: goal-loop
source_ref: GOAL §15 TrainingRun → ModelPassport producer gap
depends_on: [6a9e762640484f2bbaf8df51a6ef779b, 08ce677e8df64b8e856a43fe115b8b25]
---

# TrainingRun produces governed ModelPassport

## Scope [必填]
Wire successful training jobs into GOAL §15 model-governance metadata. When a
structured training job produces a model artifact, the training service must
write a local `validation_dossier.json`, record a validated
`ModelGovernancePassport`, register the model version with passport/dossier
refs, and expose those refs on the training job response.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/training/service.py` | Add TrainingRun → ValidationDossier → ModelPassport producer before `ModelRegistry.register_version` |
| `app/backend/app/training/store.py` | Persist `model_version`, `model_passport_ref`, and `validation_dossier_ref` on `TrainingJob` |
| `app/backend/app/main.py` | Pass `dataset_id` into `TrainingRequest` so the passport can bind a dataset ref |
| `app/backend/tests/test_training_service.py` | Assert training produces passport, dossier, and ModelVersion refs |
| `app/backend/tests/test_training_api.py` | Assert `/api/training/jobs` success response exposes governance refs |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Successful structured training with a model artifact must produce `model_passport_ref`.
2. The generated passport must bind `training_run_ref`, `dataset_refs`, feature refs, label refs, artifact hash, and validation dossier ref.
3. The registered `ModelVersion` must carry the same passport/dossier refs returned on `TrainingJob`.
4. The API response must expose the refs; UI/API callers cannot silently get an ungoverned trained model.
5. Missing artifact file must fail before model version/passport registration.

## 完成记录
- Added governance refs to `TrainingJob`.
- Added `TrainingRequest.dataset_id`.
- Added training-produced `validation_dossier.json` with model version, run, dataset, feature, label, metrics, fold count, artifact path, and artifact hash.
- Added automatic `ModelGovernancePassport` recording when `TrainingService` has a governance registry.
- Registered `ModelVersion` with `model_passport_ref` and `validation_dossier_ref`.
- Scoped validation:
  - `python -m compileall -q app/backend/app/training/service.py app/backend/app/training/store.py app/backend/app/main.py app/backend/tests/test_training_service.py app/backend/tests/test_training_api.py` -> pass.
  - `cd app/backend && python -m pytest tests/test_training_service.py tests/test_training_api.py tests/test_model_governance.py tests/test_experiments.py -q` -> 43 passed / 2 warnings.
  - `cd app/backend && python -m pytest tests/test_training_service.py tests/test_training_api.py tests/test_model_desk_m2.py tests/test_model_cards.py tests/test_model_eval.py tests/test_backtest_bridge.py tests/test_dl_trainer_fixes.py -q` -> 91 passed / 2 warnings.
  - `cd app/backend && python -m pytest -q` -> 1555 passed / 13 skipped / 283 warnings.

## 边界
- This produces governance metadata for successful structured training jobs.
- It does not load model artifacts for inference.
- It does not implement sandboxed artifact loader execution.
- It does not auto-promote runtime stage; approval remains the stage gate.
- Free-code tasks without a model artifact still do not register ghost model versions.

## 验收一句话 [必填]
Training jobs that produce model artifacts now create a validation dossier,
record a governed ModelPassport, and register the model version with those refs.
