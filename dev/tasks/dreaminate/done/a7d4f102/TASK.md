---
uuid: a7d4f102afbb4c57ac7c2e565b6a9c32
title: GOAL §10 methodology validation contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-methodology-validation
source: goal-loop
source_ref: dev/GOAL.md §10 方法学与验证
depends_on: []
---

# GOAL §10 methodology validation contract

## Scope [必填]
Add a runtime contract for strong-validation method refs, short-sample honesty,
cost/TCA requirements for production candidates, user-waived methodology
disclosure, methodology control-plane records, and DSR not being used as the
primary single-strategy live monitor.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/methodology_validation.py` | Add validation methodology, choice coverage, and live alert validators |
| `app/backend/app/research_os/__init__.py` | Export §10 methodology types |
| `app/backend/tests/test_methodology_validation.py` | Add adversarial tests for methodology overclaiming and monitoring misuse |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Short sample producing strong conclusion -> reject.
2. Strong validation missing PBO/DSR/bootstrap/honest-N/multiple testing/CPCV or walk-forward -> reject.
3. Production candidate missing cost model -> reject.
4. User-waived validation marked strong or missing responsibility -> reject.
5. Loose/exploratory/custom choice missing tradeoffs/recommendation/responsibility -> reject.
6. DSR used as primary live monitoring alert -> reject.

## 完成记录
- Added `app/backend/app/research_os/methodology_validation.py`.
- Added `app/backend/tests/test_methodology_validation.py`.
- Exported methodology validation contract types from `app.research_os`.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_document_intelligence_contract.py tests/test_methodology_validation.py -v` -> 13 passed.

## 验收一句话 [必填]
GOAL §10 now has a tested methodology validation contract. It is not yet wired
into every validation dossier producer or live monitor.
