---
uuid: c637a97f727b4e3b8c0ccf22c8369e0c
title: GOAL §4 Data Onboarding / Settings / LLM Gateway contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-onboarding-gateway
source: goal-loop
source_ref: dev/GOAL.md §4 Data Onboarding / Settings / Skill
depends_on: []
---

# GOAL §4 Data Onboarding / Settings / LLM Gateway contract

## Scope [必填]
Add a runtime governance contract for data onboarding, Settings/Secrets,
IngestionSkill, DataSourceAsset, LLMProvider/Auth/Gateway, CredentialPool, and
ModelRoutingPolicy. Cover the §4 explicit bad gates without replacing current
connectors or LLM adapters.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/onboarding_gateway.py` | Add SecretRef, IngestionSkill, DataSourceAsset, LLMProvider, CredentialPool, ModelRoutingPolicy, and Gateway call validators |
| `app/backend/app/research_os/__init__.py` | Export §4 onboarding/gateway types |
| `app/backend/tests/test_onboarding_gateway.py` | Add adversarial tests for §4 bad gates |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Agent-facing connector config containing plaintext key -> reject.
2. SecretRef revoked while skill keeps running -> reject.
3. DataSourceAsset missing license/rate_limit/retention_policy -> warn and restrict export/share.
4. Schema drift without event and downstream impact preview -> reject.
5. LLM provider credential bypassing Settings/Secrets -> reject.
6. Role agent bypassing LLM Gateway -> reject.
7. ModelRoutingPolicy missing `allowed_models`, `credential_pool_ref`, or `replay_requirement` -> reject.

## 完成记录
- Added `app/backend/app/research_os/onboarding_gateway.py`.
- Added `app/backend/tests/test_onboarding_gateway.py`.
- Exported onboarding/gateway types from `app.research_os`.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_onboarding_gateway.py -v` -> 8 passed.
  - `cd app/backend && python -m pytest tests/test_secrets_loader.py tests/test_llm_providers.py tests/test_onboarding_gateway.py -v` -> 21 passed.

## 验收一句话 [必填]
GOAL §4 now has a tested governance contract for SecretRef/IngestionSkill,
DataSourceAsset export/share limits, LLM Provider credential handling, Gateway
usage, and routing policy fields. It is not yet wired into every Settings UI,
connector, provider adapter, or role-agent call path.
