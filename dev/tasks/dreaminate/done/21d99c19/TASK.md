---
uuid: 21d99c1963b94728a399677aadb684a9
title: Settings-managed LLM connection wizard UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-onboarding-gateway
source: goal-gap
source_ref: GOAL §4 Settings/Secrets + §7 Agent Shell + §16 LLM Gateway visible connection flow
depends_on: [de77a28c069a4dc5a2c54c3e24a707d5]
completed_at: 2026-06-27
---

# Settings-managed LLM connection wizard UI

## Scope [必填]
把 `/settings/llm` 从旧的“保存配置 + 单独去安全页测试”升级为同页 Settings-managed connection flow：显示 `SecretRef` / `LLMCredentialPool` / `ModelRoutingPolicy` refs、Gateway 管理状态、auth status，并能从 provider 状态卡直接调用 `/api/llm/test`。`/settings/security` 的 LLM Providers 运维面板同步使用同一状态字段和 `authFetch`。

## 上下文 / 动机 [按需]
`de77a28c` 已把后端 configure/test/Agent runtime 接到 Settings-managed Gateway resolver，但前端仍看不到 Gateway refs，也不能在配置页内形成“保存 -> refs/status -> test”的连续工作流。本卡补可见 connection wizard seam；不声称实现 OAuth/device-code/account auth 或完整 Settings/Secrets 后端。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/LLMSettingsPage.tsx` | provider 状态卡展示 `settings_managed`、`auth_status`、`secret_ref`、`credential_pool_ref`、`routing_policy_ref`；同页测试连接；configure 成功回执只显示 refs，不显示 key，不宣称已连通 |
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | LLM Providers 面板改用 `authFetch`，同步展示 Gateway managed / auth / refs |
| `app/frontend/src/pages/LLMSettingsPage.test.tsx` | 增加 refs 不泄密、configure refs 回执、测试连接成功/失败的对抗测试 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `/api/llm/status` 返回 Settings refs 时，前端必须显示 ref，不得显示 API key。
2. `/api/llm/configure` 成功后，回执只能说写入配置和 Settings metadata，不能说已连通真模型。
3. 点击 provider 卡测试连接必须真打 `/api/llm/test`，body 带 provider。
4. Gateway test 失败时必须显示错误，不能渲染成功符号或成功文案。

## 红线 [按需]
- 前端不能持久化或展示 provider API key。
- connection test 成功只代表当前后端 resolver 可调用 provider，不等于 CI、线上部署或生产 profile 可用。
- Settings UI 不得伪装成 OAuth/device-code/account auth 已实现。

## 非目标 [按需]
不实现 OAuth/device-code/account auth，不接外部 provider 真实账号流程，不实现全 connector Settings UI，不改生产 keystore backend，不做浏览器端真实网络联调。

## 验收一句话 [必填]
用户在 `/settings/llm` 保存 provider 后能看到 Settings-managed refs 和 auth 状态，并能从同页发起 Gateway connection test；前端测试能抓住 refs 泄露、假连通和 test 失败假绿灯。

## 完成记录（2026-06-27）
- `/settings/llm` provider 状态卡显示 Gateway managed / auth status / SecretRef / Pool / Policy。
- `/settings/llm` 新增同页连接测试按钮，复用 `/api/llm/test`，成功/失败都按后端结果显示。
- configure 成功回执显示 `SecretRef`，不回显 key，不宣称 provider 已连通。
- `/settings/security` 的 LLM Providers 面板改用 `authFetch` 和同一 refs/status 字段。
- 本地验证：
  - `cd app/frontend && npm test -- --run src/pages/LLMSettingsPage.test.tsx` -> 1 file / 9 tests passed。
  - `cd app/frontend && npm test -- --run` -> 26 files / 292 tests passed。
  - `cd app/frontend && npm run build` -> `tsc && vite build` PASS，保留既有 chunk size warning。
- 边界：这是第一版 Settings-managed LLM connection UI/wizard seam，不是完整 Settings UI、OAuth/device-code/account auth、所有 connector/provider adapter、生产 keystore backend 选择、CI/线上部署或外部 LLM 实网连通证明。
