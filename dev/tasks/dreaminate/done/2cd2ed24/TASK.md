---
uuid: 2cd2ed24c9c747f8b714d55469379d32
title: Settings LLM provider health snapshot registry
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: settings-llm-provider-health
source: goal-gap
source_ref: GOAL §4 provider health / quota monitoring; TRACE §4 provider health/quota residual
depends_on: [de77a28c069a4dc5a2c54c3e24a707d5]
created_at: 2026-06-28
completed_at: 2026-06-28
---

# Settings LLM provider health snapshot registry

## Scope [必填]
新增 Settings-managed LLM provider health/quota snapshot append-only registry/API：对已登记 LLMProvider 记录 refs/hash-only health、quota、latency、checker、evidence，不保存 provider token、raw response 或 prompt/output。

## 上下文 / 动机 [按需]
GOAL §4 要求 Settings 监控 provider health 与 quota status。现有 `LLMProviderRecord` 有 `health_status` / `quota_status` 字段，`/api/llm/test` 也能临时测试连接，但没有独立可 replay 的 provider health/quota snapshot 账本，无法作为治理证据或 RAG/审计资产引用。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/onboarding_gateway.py` | 新增 `LLMProviderHealthSnapshotRecord`、validator 和 registry 存取/replay |
| `app/backend/app/main.py` | 新增 `POST /api/research-os/settings/llm_provider_health_snapshots` 与 settings summary 回显 |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖成功记录、unknown provider、bad health/quota、raw/secret payload fail-closed |
| `dev/research/TRACE.md`、`dev/state/dreaminate/state.md`、`dev/log/dreaminate/log.md` | 记录已建证据、验证和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. unknown `provider_id` 422，snapshot 不写。
2. `health_status` 只允许 ok/degraded/down/unknown，`quota_status` 只允许 ok/limited/exhausted/unknown；非法状态 422。
3. payload 带 `raw_response`、`raw_prompt`、`raw_output`、`api_key`、`token`、`secret` 或 plaintext secret marker 时 422 且不写 partial record。
4. `auth_ref` 必须是 Settings-managed SecretRef/TokenRef，且必须属于该 provider 已登记 auth_refs。
5. 成功 summary 只回显 refs/hash/status，不回显 secret、raw provider response、prompt 或 output。

## 红线 [按需]
- 不接 OAuth/device-code/account auth。
- 不把本地 snapshot 说成真实外部 provider SLA、线上监控或 quota billing 证明。
- 不保存 raw prompt/output/provider response/token/secret。

## 非目标 [按需]
不实现真实 provider polling scheduler、OAuth/device-code/account auth、生产 keyring/HSM、外部 billing/quota API、CI 或线上监控。

## 验收一句话 [必填]
Settings 可记录 LLM provider health/quota snapshot；unknown provider、bad status、非 Settings auth ref 或 raw/secret payload fail-closed，summary 只回显 refs/hash/status。

## 完成记录
- `app/backend/app/research_os/onboarding_gateway.py` 新增 `LLMProviderHealthSnapshotRecord`、`validate_llm_provider_health_snapshot()` 和 `PersistentOnboardingRegistry.record_llm_provider_health_snapshot()`；snapshot JSONL append-only/replay。
- snapshot 必须绑定已登记 `LLMProviderRecord`，`auth_ref` 必须属于 provider.auth_refs 且对应 Settings SecretRef 未 revoked。
- health status 只允许 `ok/degraded/down/unknown`，quota status 只允许 `ok/limited/exhausted/unknown`；latency 不能为负。
- `app/backend/app/main.py` 新增 `POST /api/research-os/settings/llm_provider_health_snapshots`，服务端重算 `snapshot_hash`；settings summary 新增 `llm_provider_health_snapshot_total` 和 `llm_provider_health_snapshots`。
- API parser allowlist 拒绝 `raw_response`、raw prompt/output、provider payload、token/secret 字段；summary 只回显 refs/hash/status/latency，不回显 raw response、prompt/output 或 credential。

## 验证
- `python -m compileall -q app/backend/app`：PASS。
- `python -m pytest app/backend/tests/test_onboarding_gateway.py -q`：51 passed / 2 warnings。
- `python -m pytest app/backend/tests/test_onboarding_gateway.py app/backend/tests/test_llm_providers.py app/backend/tests/test_llm_custom_and_api.py app/backend/tests/test_llm_record_replay.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py -q`：154 passed / 2 warnings。
- `python -m pytest app/backend/tests -q`：1903 passed / 13 skipped / 283 warnings。

## 边界
这是 Settings-managed LLM provider health/quota snapshot 账本，不是真实 provider polling scheduler、OAuth/device-code/account auth、生产 keyring/HSM、外部 billing/quota API、CI 或线上监控。
