---
uuid: 9c5e2a6de5144515aefdeea85bbcc39d
title: GOAL §6 document intelligence contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-document-intelligence
source: goal-loop
source_ref: dev/GOAL.md §6 Research / Document Intelligence / Mathematical Research Layer
depends_on: []
---

# GOAL §6 document intelligence contract

## Scope [必填]
Add a runtime contract for SourceDocument intake safety, EvidenceSpan structure,
span-support verification before confirmatory use, extracted claim evidence refs,
and schema-constrained privileged tool boundaries for untrusted document content.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/document_intelligence.py` | Add source intake, EvidenceSpan, extracted claim, and privileged tool validators |
| `app/backend/app/research_os/__init__.py` | Export §6 document intelligence types |
| `app/backend/tests/test_document_intelligence_contract.py` | Add adversarial tests for evidence and parser trust boundaries |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Source intake without quarantine/parser sandbox/hash/rights -> reject.
2. Network-enabled parser -> reject.
3. EvidenceSpan missing location/hash/support verification -> reject.
4. Extracted claim without EvidenceSpan -> reject.
5. Unverified span entering confirmatory claim -> reject.
6. PDF/web payload directly triggering privileged tool -> reject.

## 完成记录
- Added `app/backend/app/research_os/document_intelligence.py`.
- Added `app/backend/tests/test_document_intelligence_contract.py`.
- Exported document intelligence contract types from `app.research_os`.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_document_intelligence_contract.py tests/test_methodology_validation.py -v` -> 13 passed.

## 验收一句话 [必填]
GOAL §6 now has a tested document intelligence trust-boundary contract. It is
not yet a full parser pipeline or persistent document evidence store.
