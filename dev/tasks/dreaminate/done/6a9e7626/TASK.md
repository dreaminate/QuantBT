---
uuid: 6a9e762640484f2bbaf8df51a6ef779b
title: Research OS model governance passport registry API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-model-governance
source: goal-loop
source_ref: GOAL §15 Model Governance / ModelPassport registry gap
depends_on: [317bdbd4c03f4f82b1f611637203c27a]
---

# Research OS model governance passport registry API

## Scope [必填]
Build the first persistent ModelPassport registry/API for GOAL §15 model
governance. The slice must record validated `ModelGovernancePassport`
metadata, replay it from append-only JSONL, and expose a Research OS summary
without loading model files or changing the legacy model promotion path.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/model_governance.py` | Add `model_passport_from_dict` and `PersistentModelGovernanceRegistry` for validated JSONL model passport records |
| `app/backend/app/research_os/__init__.py` | Export the persistent registry and payload parser |
| `app/backend/app/main.py` | Add app-level model-governance registry plus `POST /api/research-os/model_governance/passports` and `GET /api/research-os/model_governance/summary` |
| `app/backend/tests/test_model_governance.py` | Cover registry replay, invalid no-write, API record/summary, and recertification failure |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Persisted passport history must replay after registry restart.
2. Missing `ValidationDossier` must reject and must not create a JSONL file.
3. API summary must show passport metadata and artifact refs without loading artifact content.
4. Material model change without recertification must reject through the API and leave no partial record.
5. Nested API payloads must round-trip into `ModelGovernancePassport` dataclasses.

## 完成记录
- Added append-only `PersistentModelGovernanceRegistry` backed by `DATA_ROOT/audit/model_governance.jsonl`.
- Added `model_passport_from_dict` to normalize nested API/JSONL payloads into typed model-governance records.
- Added Research OS model-governance endpoints:
  - `POST /api/research-os/model_governance/passports`
  - `GET /api/research-os/model_governance/summary`
- Scoped validation:
  - `python -m compileall -q app/backend/app/research_os/model_governance.py app/backend/app/research_os/__init__.py app/backend/app/main.py app/backend/tests/test_model_governance.py` -> pass.
  - `cd app/backend && python -m pytest tests/test_model_governance.py -q` -> 12 passed / 2 warnings.
  - `cd app/backend && python -m pytest tests/test_model_governance.py tests/test_platform_coverage.py tests/test_engineering_standards.py tests/test_strategy_console_s2.py -q` -> 52 passed / 2 warnings.
  - `cd app/backend && python -m pytest -q` -> 1549 passed / 13 skipped / 283 warnings.

## 边界
- This is a governance metadata registry/API.
- It does not execute training.
- It does not replace `MODEL_REGISTRY`.
- It does not load model artifacts.
- It does not promote runtime stages.
- Existing training/model promotion endpoints still need explicit GOAL §15 wiring.

## 验收一句话 [必填]
GOAL §15 now has a persistent, replayable, API-visible ModelPassport metadata
registry that refuses invalid governance records without writing partial state.
