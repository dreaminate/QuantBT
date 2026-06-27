---
uuid: 317bdbd4c03f4f82b1f611637203c27a
title: GOAL §15 Model Governance promotion contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-model-governance
source: goal-loop
source_ref: dev/GOAL.md §15 Model Governance
depends_on: []
---

# GOAL §15 Model Governance promotion contract

## Scope [必填]
Build the first runtime contract for GOAL §15 model governance. The contract
must validate model promotion fields and reject the explicit §15 bad gates:
missing ValidationDossier, external pickle direct load, high-risk model without
challenger evidence, and material model changes without recertification.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/model_governance.py` | Add `ModelGovernancePassport`, artifact manifest, safe-loading policy, recertification triggers, and promotion validator |
| `app/backend/app/research_os/__init__.py` | Export §15 model-governance types |
| `app/backend/tests/test_model_governance.py` | Add adversarial tests for the §15 rejection gates |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Model promotion missing `ValidationDossier` must reject.
2. External pickle/joblib direct loading must reject.
3. High-risk model without `challenger_result` must reject.
4. Material model change without `RecertificationRecord` must reject.
5. Torch artifact without `weights_only=True` policy must reject.
6. Project-produced pickle may pass only when producer run, hash, and sandbox policy are present.

## 完成记录
- Added `app/backend/app/research_os/model_governance.py`.
- Added `app/backend/tests/test_model_governance.py`.
- Exported model-governance types from `app.research_os`.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_model_governance.py -v` -> 7 passed.
  - `cd app/backend && python -m pytest tests/test_research_os_spine.py tests/test_research_os_rdp.py tests/test_research_asset_rag.py tests/test_model_governance.py -v` -> 26 passed.

## 验收一句话 [必填]
GOAL §15 now has a tested promotion gate for model passport fields, artifact
loading safety, challenger evidence, and recertification. It is not yet wired
into every existing model-training or registry endpoint.
