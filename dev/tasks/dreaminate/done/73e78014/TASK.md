---
uuid: 73e78014c06047de8e645db65904def5
title: Research OS settings LLM provider registry API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-onboarding-gateway
source: goal-gap
source_ref: GOAL §4 Settings / LLM Provider / SecretRef registry gap
depends_on: [c637a97f727b4e3b8c0ccf22c8369e0c]
---

# Research OS settings LLM provider registry API

## Scope [必填]
新增 Research OS Settings metadata registry：持久化 SecretRef metadata、LLMProvider metadata、LLMCredentialPool 和 ModelRoutingPolicy。它只记录 Settings-managed refs 和路由治理信息，不保存明文 API key / OAuth token / password，也不替代旧 `/api/llm/configure` 的真实 keystore 写入。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/onboarding_gateway.py` | 新增 `validate_secret_ref` 与 `PersistentOnboardingRegistry`，append-only JSONL replay Settings/LLM routing metadata |
| `app/backend/app/research_os/__init__.py` | 导出 registry 和 `validate_secret_ref` |
| `app/backend/app/main.py` | 新增 app-level `ONBOARDING_REGISTRY` 和 `/api/research-os/settings/*` API |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖 secret/provider/pool/policy replay、悬空引用拒绝、API summary、plaintext payload 拒绝 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. SecretRef metadata 不能包含明文 `sk-*`、`api_key`、password、OAuth token。
2. revoked SecretRef 必须带 `revoked_at`。
3. LLMProvider 的 `auth_refs` 必须先在 Settings registry 中登记，不能悬空。
4. CredentialPool 必须引用已登记 provider 和 SecretRef。
5. ModelRoutingPolicy 必须引用已登记 provider 和 credential pool。
6. API 收到含明文 key/token/password 的 payload 必须 422，且不写 partial JSONL。

## 验收一句话 [必填]
Research OS 现在有第一版 Settings/LLM Provider metadata registry 和 API；这仍不是完整 Secrets 后端、真实 provider adapter、role-agent Gateway 强制执行或 Settings UI。

## 完成记录（2026-06-27）
- 新增 `PersistentOnboardingRegistry`，以 append-only JSONL 记录 SecretRef、LLMProvider、LLMCredentialPool、ModelRoutingPolicy metadata，并在 replay 时 fail-closed。
- 新增 `POST /api/research-os/settings/secret_refs`、`llm_providers`、`credential_pools`、`routing_policies` 和 `GET /api/research-os/settings/summary`。
- API 统一扫描 payload，拒绝明文 credential material；provider/pool/policy 写入要求上游 refs 已登记。
- 已验证：
  - `python -m compileall -q app/backend/app/research_os/onboarding_gateway.py app/backend/app/research_os/__init__.py app/backend/app/main.py app/backend/tests/test_onboarding_gateway.py` -> success。
  - `cd app/backend && python -m pytest tests/test_onboarding_gateway.py -q` -> 13 passed / 2 warnings。
  - `cd app/backend && python -m pytest tests/test_onboarding_gateway.py tests/test_agent_os_contract.py tests/test_engineering_standards.py tests/test_strategy_console_s2.py tests/test_agent_runtime_research_graph.py -q` -> 64 passed / 2 warnings。
  - `cd app/backend && python -m pytest -q` -> 1544 passed / 13 skipped / 283 warnings。
- 边界：这不是真实 secret value storage、provider adapter、Gateway runtime enforcement、Settings UI、connection test wizard 或 full connector integration。
