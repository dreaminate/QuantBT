---
uuid: 4b7e2c19b17d42f5a5346f7dd5c0379a
title: Settings SecretValue storage for SecretRef-backed connectors
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-settings-secrets
source: goal-gap
source_ref: GOAL §4 Settings/Secrets; GOAL §16 secret handling standard
depends_on: [e65a6e9664d94103bcab30cf9ebd0996]
completed_at: 2026-06-27
---

# Settings SecretValue storage for SecretRef-backed connectors

## Scope [必填]
把 Settings Data Connector 的 SecretRef 从纯 metadata 扩到真实 `SecureKeystore` value 写入：新增专用 SecretValue endpoint，Settings summary/UI 只显示 stored/backend 状态，不回显 secret；connector check/run 在 SecretRef metadata 声明 `keystore:<name>` 时必须确认 value 存在后才调用 checker/runner。

## 上下文 / 动机 [按需]
`e65a6e96` 已把 Settings 数据接入链路闭合到 accepted MarketDataUseValidation，但 §4/§16 仍把 “SecretRef metadata 不等于真实 secret value backend” 标成缺口。LLM 配置已有 `/api/llm/configure -> SecureKeystore + SecretRef metadata` 专用路径，Data Connector 面板缺同等能力。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 SecretValue parser、keystore-ref 映射、stored summary、`POST /api/research-os/settings/secret_values`、connector check/run declared-keystore-value gate |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖 value 入 keystore、summary 不回显、revoked fail-closed、declared keystore missing fail-closed、checker 可用 keystore value |
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | Data Connectors panel 显示 SecretRef value stored 状态，新增 password 输入和 Store value 按钮 |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | 覆盖 SecretValue POST body 和页面不泄露 value |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. SecretValue endpoint 可以接收 plaintext credential，但 response、summary、UI 不得回显 value。
2. 普通 SecretRef metadata endpoint 仍拒绝 plaintext payload。
3. 已 revoked SecretRef 不能写入 secret value，keystore 不产生 partial write。
4. SecretRef metadata 声明 `keystore:<name>` 但 backend 缺 value 时，connector checker/runner 前 fail-closed，不调用 checker/runner。
5. Fake checker 只能通过 keystore ref 自行 fetch value；Settings endpoint 不把 secret value 作为 response 或 summary 传回。

## 红线 [按需]
- 不把 stored value 状态说成 provider 真连通。
- 不在 registry/summary/QRO/UI 回显 api key、token、secret 或 note 中的秘密。
- 不把内存 keystore 测试说成生产 keyring/HSM 证明。
- 不把本地测试通过说成 CI、线上或用户验收。

## 非目标 [按需]
不实现 OAuth/device-code/account auth，不选择生产 keystore backend，不新增真实 connector adapter，不做全资产自动同步，不证明外部 provider 实网连通。

## 验收一句话 [必填]
Settings Data Connector 能把 SecretRef 对应 value 写进 `SecureKeystore`，summary/UI 只暴露 stored/backend 状态；revoked 或缺 declared keystore value 的路径必须 fail-closed。

## 完成记录
- 新增 `POST /api/research-os/settings/secret_values`，专门接收 secret value，写入 `SecureKeystore`，并把 SecretRef metadata 的 `access_audit` 补成 `keystore:<name>`。
- SecretRef summary 返回 `keystore_refs`、`secret_value_stored`、`keystore_backend`，不返回 value 或 note。
- Data Connector check/run 在 SecretRef metadata 声明 keystore ref 时先确认 value 存在；缺 value 时 422 且不调用 checker/runner。
- Settings 安全页 Data Connectors panel 新增 per-SecretRef stored/missing 状态、password 输入和 Store value 按钮。
- 验证：`tests/test_onboarding_gateway.py` **37 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **96 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- 边界：这是 Settings-managed secret value storage + declared keystore presence gate，不是 OAuth/device-code/account auth、生产 keyring/HSM 选择、真实 connector adapter、外部 provider 实网连通、CI、线上或用户验收。
