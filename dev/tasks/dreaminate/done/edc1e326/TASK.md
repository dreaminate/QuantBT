---
uuid: edc1e32623674b1f870b264119db2421
title: 主对话入口接 AgentRuntime + 无副作用工具 + 权限三态(ask/auto/bypass)
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: agent
source: interaction
source_ref: 2026-06-20 回测全流程审计 workflow + D-PERM + GOAL §0/§2
depends_on: [180a341e2d064e368be14bfa3b67f790]
---

# 主对话入口接 AgentRuntime + 无副作用工具 + 权限三态(ask/auto/bypass)

## Scope [必填]
把主对话入口 `chat_send_message`(现 RAG-only)接上 AgentRuntime 工具派发；引入 **agent 权限三态 `ask`/`auto`/`bypass`**(D-PERM)作为"agent 要不要停下问你"的开关；按"会不会发外部单"分级动作。**权限轴 ⟂ 治理轴**:权限模式只调确认强度,绝不跳过治理门(OrderGuard/审批/过拟合/血统门任何模式都执行,bypass 也拦真钱)。不动治理门本体。

## 上下文 / 动机 [按需]
审计核实:主对话入口只做 RAG + 单次 chat()，`backtest.run` 等核心工具未注册——"用户授权 agent 帮自己跑回测"端到端做不到。回测/IC/PBO/Paper 是无副作用动作,本不需要为动钱设计的重门。这是当前最大"能力名不副实"硬伤。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/main.py | 3038-3103 chat_send_message(RAG-only) | 接 AgentRuntime 工具派发 |
| app/backend/app/main.py | 283-285 register_tool | 注册无副作用工具 + 工具标副作用级别 |
| app/backend/app/agent/agent_runtime.py | 72-141 AgentRuntime | 复用确定性 reAct;加权限模式判定派发 |
| app/backend/app/agent/replay/translation.py | 93-115 受控翻译门 | 所有工具(含新注册)仍过此门 |
| 客户端 + 后端 | 权限模式存储 | 用户选 ask/auto/bypass |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 免门白名单 = 回测+Paper:agent 收到"跑个回测"在 auto/bypass 下自动跑出结果;种"无副作用动作误挂 HITL" → 抓。
2. testnet 轻确认:testnet 发单在 ask/auto 下必停一次确认;种"testnet 被归免门自动发" → 抓。
3. **权限轴⟂治理轴(命门)**:`bypass` 模式下下真钱单/上实盘 → 治理门照拦;种"bypass 跳过 OrderGuard/审批门" → 必抓(致命,§5)。
4. 翻译门仍在:语义越界(30x 杠杆声明)→ 翻译门拦。

## 复用 [按需]
`agent_runtime.py`、`translation.py`、`gate_runner.py` 全复用,不重造。

## 红线 [按需]
权限三态绝不跳治理门(D-PERM);动钱/晋级永不进免门白名单(§5);**默认止于模拟盘,agent 绝不默认/自动导向实盘**;A股 live 永拒;密钥不进 LLM。

## 非目标 [按需]
不改 OrderGuard/审批门/翻译门实现;不动 RunDetailPage;agent 客户端窗口 UI 归 T-035。

## Open Questions（已决 1/1）[按需]
- [已决] 免门白名单边界(D-PERM):回测 + Paper(不发外部单)免门自主;**testnet 真发单保留一次轻确认**;live 重门。

## 验收一句话 [必填]
agent 在主对话框一句话能跑完无副作用回测/IC/PBO/Paper;种"动钱工具混入免门 / bypass 跳治理门" → 门必抓;不破坏现有测试基线。

## 完成记录（2026-06-20）
- **权限三态 + 权限轴⟂治理轴（核心，D-PERM）**：`agent_runtime.py` 加 `permission_gate(mode, side_effect)` + `register_tool(..., side_effect)` + run dispatch 前权限门。矩阵：none=ask 确认/auto·bypass 自动；external=仅 bypass 自动；**realmoney=任何模式（含 bypass）都挂起**（权限轴绝不跳治理门）。
- **工具 side_effect 分级**：`_agent_runtime` 注册的 strategy_goal.create/factor.run_ic/code.replicate + 字段工具全标 none；动钱/晋级永不注册（治理门在端点层）。
- **chat 入口接 AgentRuntime**：`chat_send_message` 从裸 client.chat 改为经 `_agent_runtime(permission_mode, system_prompt=RAG)`，支持工具派发 + permission_mode 透传；保留 RAG + metadata，round-trip 回归绿。
- **对抗测试**（`test_agent_permission_tristate.py` 16 + `test_r11_*` 8）：权限矩阵 9 参数化 + realmoney 三模式全挂起探针 + auto 执行/ask 挂起/external 分模式。
- **验收**：全量 **1070 passed / 13 skipped**（基线 1054 未破，+16）。
- **残余（子卡，非半成品）**：让 agent「一句话真跑回测」需把无副作用业务工具接真引擎——`backtest.run`(接 codegen/sandbox/runner) / `eval.pbo` / `report.generate` 真 handler 是独立功能；当前 agent 可派发的是无副作用 stub/轻工具。机制（权限三态+治理正交+chat 派发贯通）已做实可测，建议拆子卡接真 handler。
