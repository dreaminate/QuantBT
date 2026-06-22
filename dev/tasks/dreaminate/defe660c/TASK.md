---
uuid: defe660cad5343bcaf1f01e351b4fb9d
title: DS-2 造站接真——Agent台默认接真 + 无key slot-filling 真落库 + Hermes 预设（Fork1=C+Hermes）
status: todo
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: agent-frontend
source: developer-claude
source_ref: 2026-06-22 D-DELIVERY-SLICE · audit blocker #1/#2 + Hermes auth
depends_on: []
---

# DS-2 造站接真

## Scope [必填]
让陌生人「对话生成策略」真成立：① Agent 工作台默认 `liveMode=true`、mock autoplay 仅作显式「看演示」入口且全程 MockBadge（blocker #1）；② 无 LLM key 时 DevLocalLLM 不死兜底，改 slot-filling 追问回路（缺 asset_class/horizon/objective 就问）+ `strategy_goal.create` 真校验落库产可下游引用的 goal_id（blocker #2）；③ **Hermes auth 预设**（Fork1）：onboarding/Settings 加引导「用 Claude Code/Codex 订阅（经 Hermes 等本地 OAuth 代理）」——复用已有 `OpenAICompatibleLLM` custom provider，预填 `http://localhost:<port>/v1` + 文档教跑 Hermes，不自实现 OAuth。

> **前后端分工澄清（2026-06-22）**：blocker #2 的**后端核已 done**（commit `6726c4f`：新 `strategy_goal_store.py` 的 `StrategyGoalStore.create_from_args` 校验落库产真 goal_id + slot-filler 兜底 + §3 缺槽不伪造；`main.py` strategy_goal.create 回显 lambda→真 handler）；`StrategyGoalSlotFiller` 与 `POST /api/llm/configure` 也早已存在。**本卡剩前端/文档**：① liveMode 默认 true + 演示挂 MockBadge ② 新 `LLMSettingsPage.tsx`（Hermes 预设 UI，接已有 configure 端点）③ 后端 agent_workbench_stream 的 tool_end 带真 run_id（为 DS-3 铺路）④ Hermes onboarding 文档。status 仍 todo（前端未做）。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/frontend/.../AgentWorkbenchPage.tsx | 191-196 默认 autoplay | 默认 liveMode=true + MockBadge |
| app/backend/app/agent/llm_client.py | 113 DevLocalLLM 兜底 | 未命中 → slot-filling 追问 |
| app/backend/app/main.py | 368 strategy_goal.create lambda | 接真 StrategyGoal 校验+落库产 goal_id |
| app/backend/app/agent/llm_providers.py | 327 OpenAICompatibleLLM | Hermes 预设复用（custom provider） |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 无 key + 自然语言（非关键词）→ slot-filling 追问而非静默兜底；填全 → strategy_goal.create 产真 goal_id（可被 DS-1 backtest 消费）。
2. Hermes 预设：配 custom base_url → make_llm_client 真用该端点（非 DevLocalLLM）。

## 验收一句话 [必填]
陌生人（含无 key / 用 Hermes 订阅）能对话产出真 goal_id；Agent 台默认接真不放假绿灯 mock；不破基线。
