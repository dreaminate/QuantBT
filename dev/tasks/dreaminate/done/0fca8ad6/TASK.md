---
uuid: 0fca8ad65f93414eb4ec9d3ea6407d5b
title: Settings Generic REST connector YAML adapter
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-settings-data-onboarding-connectors
source: goal-gap
source_ref: GOAL §4 Data Onboarding Settings provider adapters; GOAL §11 DataSource/IngestionSkill extensibility
depends_on: [f11f8c4c87594a05ad4da74f61ebec9b]
completed_at: 2026-06-27
---

# Settings Generic REST connector YAML adapter

## Scope [必填]
让 Settings-managed `IngestionSkill.connector_config` 可以声明 `connector_name=generic_rest` 和 `generic_rest_yaml`，由后端 Settings connector resolver 构造 `GenericRESTConnector`，再复用现有 check/run/DatasetVersion/schema/update/field mapping/PIT/MarketDataUse 链路。

## 上下文 / 动机 [按需]
`adf0c2a4` / `a6dcb50f` 已覆盖 Tushare 与 Binance hardcoded adapters；`f11f8c4c` 已让 Settings UI 可编辑 field mapping/PIT。但 GOAL §4 的多源接入不能靠每个 provider 都硬编码。仓库已有 `GenericRESTConnector`，Settings resolver 还不能把 per-skill YAML config 传进去。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | `_settings_connector_for_skill` 支持 `generic_rest` / `generic_rest_yaml` / `generic_rest_config`，构造 `GenericRESTConnector` |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖 Generic REST check/fetch 通过 Settings registry adapter 写 DatasetVersion/schema/update，不联网、不回显 secret |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档 Settings Generic REST adapter、本地测试和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `connector_name=generic_rest` 缺 YAML/config 时必须记录 `status=failed` / `ok=false` 的 audited check，不得假绿或继续 run。
2. Generic REST health/fetch 必须来自 per-skill config，不能误走全局 registry singleton。
3. mocked HTTP response 能写 DatasetVersion/schema/update，证明 Settings runner 调用了 GenericRESTConnector。
4. response/summary 不回显 SecretValue 或 raw credential。
5. 仍不声称真实外网 provider 连通。

## 红线 [按需]
- 不把 Generic REST YAML 当成 trusted code 执行；只传给现有 parser/config。
- 不绕过 Settings DataSource/IngestionSkill/SecretRef/no-auth gates。
- 不把 mocked HTTP 证明说成外网 provider 实网连通。

## 非目标 [按需]
不实现完整 provider catalog、OAuth/device-code/account auth、生产 keyring/HSM、真实外网连通、scheduler、全资产自动同步、下游 strategy auto-injection、CI 或线上部署。

## 验收一句话 [必填]
Settings IngestionSkill 能用 per-skill Generic REST YAML 走默认 checker/runner，并产生受现有 gate 保护的 DatasetVersion/schema/update。

## 完成记录
- 后端 Settings resolver 新增 `connector_name=generic_rest` / `generic_rest_yaml` / `generic_rest_config` 分支，从 per-skill config 构造 `GenericRESTConnector`，并拒绝 `auth.static_value`。
- Generic REST adapter 返回 YAML 内的真实 `connector_name`，所以 check capability ref、run audit `secret:none:<connector_name>` 和 DatasetVersion/source metadata 不写成固定 `generic_rest`。
- 新增测试覆盖无 SecretRef 的 Generic REST YAML check/run：mocked `health_check()` / `fetch()` 证明调用来自 per-skill YAML config，并写 DatasetVersion、schema probe、IngestionSkillUpdate。
- 新增失败测试覆盖缺 YAML/config：返回 audited failed check，`ok=false`，不伪装 capability，不泄露 `api_key` / `sk-live` / `static_value`。
- 验证：`pytest app/backend/tests/test_onboarding_gateway.py -q` → **45 passed / 2 warnings**；`pytest app/backend/tests/test_connectors.py app/backend/tests/test_asset_lifecycle.py app/backend/tests/test_onboarding_gateway.py app/backend/tests/test_llm_custom_and_api.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_data_quality.py -q` → **116 passed / 2 warnings**；`python -m compileall -q app/backend/app` → PASS。
