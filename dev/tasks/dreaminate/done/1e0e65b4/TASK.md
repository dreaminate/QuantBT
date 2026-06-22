---
uuid: 1e0e65b4385f4161a49cb73ec9e9f735
title: 组合消费者——agent 可调组合三角 gate（SEQ-CONSUMER=A · C full-fat 触发器）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: agent
source: developer-claude
source_ref: 2026-06-22 D-WAVE1A SEQ-CONSUMER=A（C full-fat + 加组合消费者卡）
depends_on: [46f1cb3c60c84a7cb49a87b4418591ea]
---

# 组合消费者——agent 可调组合三角 gate

## Scope [必填]
给 C 的组合三角 gate（`portfolio/gate.py::gate_portfolio`）一个**真 run 触发器**：评审验证 `optimize_portfolio` 当前无产品消费者（scaffolding-ahead-of-demand），SEQ-CONSUMER=A 决定本波连消费者一起落，使「组合层守门」不是悬空件。leader 自 mint 自分配（不走 pool，承 D-DESK-EPIC 流程先例）。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/agent/business_tools.py | 5b `_portfolio_gate` + register | 新 `portfolio.gate` 工具（agent 调组合 gate，预览只读 side_effect=none） |
| app/backend/app/portfolio/gate.py | gate_portfolio | 被消费的单一源组合 gate（C 卡建） |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. agent `portfolio.gate` 工具真跑组合 gate：无 alpha 组合 → color≠green、PBO=N/A（见 `test_agent_business_tools_a4.py::test_portfolio_gate_tool_no_alpha_not_green`）。
2. 工具 side_effect 恒 none（预览不记账）：被 `test_business_tools_all_side_effect_none` 覆盖；工具名不含 order/promote/动钱（`test_no_money_or_promote_tool_registered`）。

## 验收一句话 [必填]
agent 能调组合三角 gate 拿到诚实裁决（gate 不再悬空）；不破基线。

## 实现落账（done · 2026-06-22 · D-WAVE1A · 随 C 实装）
**实装**：`agent/business_tools.py` 新 `portfolio.gate` 工具（`register_tool(side_effect="none")`）——agent 给 weights+asset_returns+markets → 调 `gate_portfolio(record=False)` 预览 → 返 color/pbo/dsr/honest_n/config_hash/诚实措辞。gate 从「无消费者」变为「agent 可真调」。

**门必抓**：`test_agent_business_tools_a4.py::test_portfolio_gate_tool_no_alpha_not_green`（无 alpha→不达 green、PBO=N/A、config_hash 复用单一源）+ 既有 `test_business_tools_all_side_effect_none`/`test_no_money_or_promote_tool_registered` 自动覆盖新工具（side_effect=none、非动钱）。全量见 C 卡 1258 passed。

**诚实残余**：production 组合 **promote 流**（record=True，honest-N 真记账）尚无端点真调用——`gate_portfolio(record=True, ledger, returns_store)` 能力已具备，缺一个 production 组合 promote 端点把它接进治理流（与 C 卡残余①同源）。本卡只落 agent 预览消费者（gate 不再悬空），promote 注入留后续。
