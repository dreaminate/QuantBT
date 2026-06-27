---
uuid: 08ce677e8df64b8e856a43fe115b8b25
title: Model Registry promotion requires governed model passport
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-model-governance
source: goal-loop
source_ref: GOAL §15 Model Registry promotion / ModelPassport wiring gap
depends_on: [317bdbd4c03f4f82b1f611637203c27a, 6a9e762640484f2bbaf8df51a6ef779b]
---

# Model Registry promotion requires governed model passport

## Scope [必填]
Wire GOAL §15 ModelPassport governance into the legacy `ModelRegistry.promote`
path. Promotion to `staging` or `production` must reference a previously
recorded `ModelGovernancePassport`; the passport must match the model version
being promoted, and its passport/dossier refs must travel into the approval
gate evidence.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/experiments/store.py` | Add `model_passport_ref` / `validation_dossier_ref` metadata and fail-closed passport validation before staging/production promotion |
| `app/backend/app/main.py` | Inject `MODEL_GOVERNANCE_REGISTRY` into `MODEL_REGISTRY` and pass API `model_passport_ref` through `/api/models/{model_id}/promote` |
| `app/backend/tests/test_model_governance.py` | Add ModelRegistry/API tests for missing, unrecorded, mismatched, and accepted passport refs |
| `app/backend/tests/test_approval_gates.py` | Update approval-gate registry tests to provide a passport fixture |
| `app/backend/tests/test_model_desk_m2.py` | Update Model Desk staging fixture to record a real passport before opening a promote gate |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Staging/production promotion without `model_passport_ref` must 422/raise before opening a gate.
2. Unknown passport refs must fail closed.
3. Passport refs whose `model_version_ref` points at another model/version must fail closed.
4. Accepted promotion must carry `model_passport_ref` and `validation_dossier_ref` into approval evidence.
5. Existing Model Desk and approval tests must not bypass §15 by using ungoverned fixtures.

## 完成记录
- `ModelVersion` now stores optional `model_passport_ref` and `validation_dossier_ref`.
- `ModelRegistry.promote()` now validates `model_passport_ref` for `staging` / `production` through the injected governance registry.
- `/api/models/{model_id}/promote` accepts and forwards `model_passport_ref`.
- `MODEL_REGISTRY` is constructed with `MODEL_GOVERNANCE_REGISTRY`.
- Scoped validation:
  - `python -m compileall -q app/backend/app/experiments/store.py app/backend/app/main.py app/backend/tests/test_model_governance.py app/backend/tests/test_approval_gates.py app/backend/tests/test_model_desk_m2.py` -> pass.
  - `cd app/backend && python -m pytest tests/test_model_governance.py tests/test_approval_gates.py tests/test_model_desk_m2.py tests/test_experiments.py tests/test_hypothesis_run_wiring.py -q` -> 75 passed / 2 warnings.
  - `cd app/backend && python -m pytest tests/test_model_governance.py -q` -> 17 passed / 2 warnings.
  - `cd app/backend && python -m pytest -q` -> 1554 passed / 13 skipped / 283 warnings.

## 边界
- This wires ModelPassport governance into Model Registry promotion gates.
- It does not execute training.
- It does not load model artifact bytes.
- It does not implement a TrainingRun-to-passport producer.
- It does not auto-promote runtime stages; approval still controls the actual stage flip.

## 验收一句话 [必填]
Model Registry promotion to staging/production now fails closed unless the
model version is backed by a previously recorded, matching ModelPassport.
