---
uuid: de77a28c069a4dc5a2c54c3e24a707d5
title: Settings-managed LLM Gateway runtime enforcement
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-onboarding-gateway
source: goal-gap
source_ref: GOAL §4 Settings/Secrets + §7 Agent Shell + §8 Governance spine + §16 LLM Gateway enforced
depends_on: [73e78014c06047de8e645db65904def5]
completed_at: 2026-06-27
---

# Settings-managed LLM Gateway runtime enforcement

## Scope [必填]
把旧 `/api/llm/configure`、`/api/llm/test` 和 role-agent runtime LLM 解析接到 Settings-managed SecretRef / LLMProvider / LLMCredentialPool / ModelRoutingPolicy。明文 provider credential 仍只进 `SecureKeystore`，Agent runtime 不从 env key 或裸 provider SDK 取真实模型；没有合格 Settings route 时只允许 DevLocal fallback 或显式失败。

## 上下文 / 动机 [按需]
`73e78014` 已有 Settings/LLM Provider metadata registry，但 state/TRACE 仍标明“真实 secret value storage、provider adapter、connection test wizard 和 role-agent Gateway runtime enforcement 待实现”。本卡推进其中的 runtime enforcement seam；不声称完成 Settings UI、OAuth/device code、所有 provider adapter 或完整 Gateway audit UI。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/agent/llm_providers.py` | 新增 Settings-managed provider metadata ensure、Gateway route validation 和 `make_settings_managed_llm_client`；role-agent 路径忽略 env key，只用 keystore + registry |
| `app/backend/app/agent/__init__.py` | 导出 Settings-managed LLM Gateway helpers |
| `app/backend/app/research_os/onboarding_gateway.py` | `validate_llm_gateway_call` 可校验 SecretRef metadata，revoked/missing SecretRef 拒绝 |
| `app/backend/app/main.py` | `/api/llm/configure` 同步写 SecretRef/Provider/Pool/Policy metadata；`/api/llm/test` 与 `_current_agent_llm` 走 Gateway resolver；reload secrets 后补 metadata |
| `app/backend/tests/test_llm_custom_and_api.py` | 覆盖 configure metadata、revoked SecretRef 阻断、env key 不能绕 Settings、Gateway 使用 keystore 而非 env |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `/api/llm/configure` 提交明文 key 后，响应/status/Settings metadata 不能回显 key，只能暴露 SecretRef。
2. SecretRef 被 revoke 后，`/api/llm/test` 不能继续静默调用 provider，必须返回 explicit Gateway rejection。
3. 只有 `OPENAI_API_KEY` env、没有 keystore + Settings metadata 时，role-agent Gateway resolver 不能构造真实 OpenAI client。
4. env key 与 keystore key 同时存在时，Gateway resolver 必须使用 keystore SecretRef 对应值，不能使用 env key。

## 红线 [按需]
- LLM provider token 不能进入 LLM / RAG / 日志 / 导出包。
- role agent 不能绕过 LLM Gateway 调 provider。
- SecretRef revoked 后不能静默继续运行。

## 非目标 [按需]
不实现 OAuth/device-code/account auth，不实现完整 Settings UI，不接所有 provider SDK，不做外部网络真实 provider 联调，不把 DevLocal fallback 包装成 production provider success。

## 验收一句话 [必填]
Settings 配置 LLM provider 后生成 SecretRef/Provider/Pool/Policy 元数据，role-agent 和 connection test 经 Gateway 验证后才取 keystore；revoked/missing/裸 env key 路径会被测试抓住。

## 完成记录（2026-06-27）
- 新增 `make_settings_managed_llm_client`：真实 provider 解析只认 `SecureKeystore` + `PersistentOnboardingRegistry`；env key 不作为 role-agent credential 来源。
- `/api/llm/configure` 继续把明文 key 写入 `SecureKeystore`，同时写入 Settings metadata refs；响应只返回 `secret_ref` / `credential_pool_ref` / `routing_policy_ref`。
- `/api/llm/status` 增加 settings-managed 状态；`/api/llm/test` 改走 Gateway resolver；`_current_agent_llm` 改走 Gateway resolver，坏配置只 fallback DevLocal 并写 warning。
- `validate_llm_gateway_call(..., secrets=...)` 新增 missing/revoked SecretRef 检查。
- 本地验证：
  - `cd app/backend && python -m pytest tests/test_llm_custom_and_api.py tests/test_onboarding_gateway.py -q` -> 29 passed / 2 warnings。
  - `cd app/backend && python -m compileall -q app` -> PASS。
  - `cd app/backend && python -m pytest tests/test_llm_custom_and_api.py tests/test_onboarding_gateway.py tests/test_llm_providers.py tests/test_llm_record_replay.py tests/test_agent_runtime_research_graph.py tests/test_agent_business_tools_a4.py tests/test_strategy_console_s2.py tests/test_engineering_standards.py -q` -> 132 passed / 2 warnings。
  - `cd app/backend && python -m pytest -q` -> 1585 passed / 13 skipped / 283 warnings in 128.02s。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️ PASS。
- 边界：这是真实 keystore + Settings metadata + Gateway runtime enforcement seam，不是完整 Settings UI、OAuth/device-code/provider account auth、全 provider adapter、CI/线上部署或真实外部 LLM 连接证明。
