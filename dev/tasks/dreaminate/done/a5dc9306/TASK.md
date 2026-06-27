---
uuid: a5dc93060aeb495cb60c9942e638c93d
title: Settings LLM provider health snapshot UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: settings-llm-provider-health
source: goal-gap
source_ref: GOAL §4 provider health / quota monitoring; TRACE §4 Settings wizard residual
depends_on: [2cd2ed24c9c747f8b714d55469379d32]
created_at: 2026-06-28
completed_at: 2026-06-28
---

# Settings LLM provider health snapshot UI

## Scope [必填]
把 Settings LLM provider health/quota snapshot registry/API 接到 LLM Settings 页：用户可基于已登记 provider/auth_ref 记录 refs/hash-only health snapshot；不做真实 provider polling scheduler、OAuth/device-code/account auth 或外部 billing/quota API。

## 上下文 / 动机 [按需]
`2cd2ed24` 已建 `LLMProviderHealthSnapshotRecord` 和 API，但 `/settings/llm` 只能配置与测试连接，不能把 provider health/quota 证据写回 Settings 账本。GOAL §4 的 Settings wizard 还缺这一层可见操作。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/LLMSettingsPage.tsx` | 读取 `/api/research-os/settings/summary` 的 `llm_providers` / `llm_provider_health_snapshots`，新增 health snapshot 表单和记录结果 |
| `app/frontend/src/pages/LLMSettingsPage.test.tsx` | 覆盖成功提交、缺 auth_ref 前端阻断、失败诚实显示、不把 raw/secret 字段放入 payload |
| `dev/research/TRACE.md`、`dev/state/dreaminate/state.md`、`dev/log/dreaminate/log.md` | 记录已建 UI 接线、验证和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 缺 Settings provider/auth_ref：前端禁用并阻断提交，不调用 snapshot API。
2. 成功记录：payload 只包含 `snapshot_ref/provider_id/auth_ref/checked_at/checker_ref/status/quota/latency/response_hash/capability_refs/evidence_refs/error_code`，不得包含 api_key、token、raw_response、raw_payload。
3. 后端 422：UI 显示失败，不追加假 snapshot，不显示成功。
4. summary 展示只用 refs/hash/status，不显示 API key。

## 红线 [按需]
不能把 `/api/llm/test` 的真实 provider response 原文、prompt/output、token、secret 或 API key 写入 health snapshot。UI 成功文案只能说“snapshot 已记录”，不能说真实线上监控或 CI 已生效。

## 非目标 [按需]
不做自动 polling scheduler、真实外部 billing/quota API、OAuth/device-code/account auth、生产 keystore backend、CI 或线上监控。

## 验收一句话 [必填]
种 raw/secret payload 或缺 auth_ref → 前端门必抓；成功只提交 refs/hash-only snapshot payload，并保持现有 LLM Settings 测试基线通过。

## 完成记录
- 新增 `/settings/llm` Provider health snapshot 面板，读取 `/api/research-os/settings/summary` 的 `llm_providers` / `llm_provider_health_snapshots`。
- snapshot 表单绑定已登记 provider/auth_ref，只提交 status/quota/latency/checker/response_hash/capability_refs/evidence_refs/error_code；UI 不提供 raw response、prompt/output、token、secret 或 API key 字段。
- 成功记录后刷新 Settings summary；后端 422 只显示失败，不追加假 snapshot。

## 验证
- `npm --prefix app/frontend test -- LLMSettingsPage.test.tsx`：**1 file / 12 tests passed**。
- `npm --prefix app/frontend test`：**30 files / 341 tests passed**。
- `npm --prefix app/frontend run build`：**PASS**（保留既有 Vite chunk-size warning）。

## 边界
这是本地 Settings LLM health/quota snapshot UI 接线，不是真实 provider polling scheduler、OAuth/device-code/account auth、外部 billing/quota API、生产 keystore backend、CI 或线上监控。
