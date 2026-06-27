---
uuid: 051144a808d443d786ddea8be0333dbc
title: Governed model artifact loader guard
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-model-governance
source: goal-loop
source_ref: GOAL §15 artifact loading safety gap
depends_on: [317bdbd4c03f4f82b1f611637203c27a, fb378e4256ec41ba9a9de137382a8fdc]
---

# Governed model artifact loader guard

## Scope [必填]
Close the existing model artifact loader gap in GOAL §15. Runtime model loading
must refuse ungoverned pickle/joblib artifacts and must load torch checkpoints
with `weights_only=True`.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/training/lib.py` | Require adjacent `validation_dossier.json` + matching artifact hash before pickle/joblib load; switch torch checkpoint load to `weights_only=True` |
| `app/backend/tests/test_training_service.py` | Add regression tests for missing dossier and hash mismatch rejection |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Pickle/joblib artifact without `validation_dossier.json` must reject before `pickle.load`.
2. Pickle/joblib artifact whose dossier hash does not match file bytes must reject.
3. Symlinked pickle/joblib artifact must reject.
4. Existing training-produced pickle artifacts must still load because `fb378e42` writes a dossier and hash.
5. Existing DL `.pt` prediction tests must pass under `torch.load(..., weights_only=True)`.

## 完成记录
- Added loader-side `validation_dossier.json` check for `.pkl` / `.joblib` artifacts.
- Added loader-side artifact sha256 recomputation and dossier hash comparison.
- Rejected symlinked serialized artifacts.
- Switched DL checkpoint load from `weights_only=False` to `weights_only=True`.
- Scoped validation:
  - `python -m compileall -q app/backend/app/training/lib.py app/backend/tests/test_training_service.py` -> pass.
  - `cd app/backend && python -m pytest tests/test_training_service.py tests/test_training_runner.py tests/test_backtest_bridge.py tests/test_dl_trainer_fixes.py -q` -> 49 passed / 2 warnings.
  - `cd app/backend && python -m pytest tests/test_training_service.py tests/test_training_runner.py tests/test_training_api.py tests/test_model_desk_m2.py tests/test_model_cards.py tests/test_model_eval.py tests/test_backtest_bridge.py tests/test_dl_trainer_fixes.py tests/test_model_governance.py -q` -> 118 passed / 2 warnings.
  - `cd app/backend && python -m pytest -q` -> 1557 passed / 13 skipped / 283 warnings.

## 边界
- This is a loader guard for local training artifacts.
- It does not implement a separate sandbox process for artifact inspection.
- It does not add remote artifact storage.
- It does not auto-promote runtime stages.
- It does not prove live model serving is safe.

## 验收一句话 [必填]
Local model loading now refuses ungoverned pickle/joblib artifacts and uses
`weights_only=True` for torch checkpoints.
