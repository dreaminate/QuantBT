---
uuid: 180a341e2d064e368be14bfa3b67f790
title: 核验 agent tool_call 前端派发是否旁路受控翻译门（R11 前端缺口审计）
status: todo
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: verification
source: interaction
source_ref: 2026-06-20 回测全流程审计 workflow（D4 open question）+ R11 + GOAL §2
depends_on: []
---

# 核验 agent tool_call 前端派发是否旁路受控翻译门（R11 前端缺口审计）

## Scope [必填]
核验前端拿到 agent 产出的 tool_call（尤其后端未注册的 `backtest.run` 等）后**怎么"继续派发"**——是经过受控翻译门 + deny-by-default 策略门，还是前端直接打 backend 端点绕过 R11；只做核验 + 对抗测试坐实，不做功能扩展（若坐实是缺口，升级为单独修复卡）。

## 上下文 / 动机 [按需]
审计发现 `register_tool` 仅注册 3 个工具，`main.py` 注释自承"正式 backend 调用由前端继续派发"。这段前端派发逻辑本次未深入，标为未验证——若前端绕过门，R11"LLM 绝不当控制器"在前端侧就有缺口。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/main.py | 283-285 register_tool（仅 3 工具） | 核验：未注册工具的 tool_call 谁执行 |
| app/backend/app/agent/agent_runtime.py | 72-141 AgentRuntime | 确认确定性派发边界 |
| app/backend/app/agent/replay/translation.py | 93-115 受控翻译门 | 确认前端路径是否也过此门 |
| app/frontend/ | agent 派发逻辑（实现时定位） | 查前端拿 tool_call 后调哪个 backend 端点 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 旁路探针：构造一个前端派发的 `backtest.run` / 下单类 tool_call，断言它必经受控翻译门 + 策略门；种"前端直调 backend 端点不过门" → 测试必抓（证明非 no-op）。
2. 变异：翻译门被注释 / 前端直连 backend → 测试必红。

## 复用 [按需]
`tests/test_realmoney_audit_killswitch.py`（T-025 绕门审计不变量模式），扩展复用。

## 红线 [按需]
R11 LLM 绝不当控制器——前端派发若旁路门 = 安全治理不变量缺口，坐实即按 RULES §5 停工报告、不擅自继续。

## 非目标 [按需]
不在本卡修复缺口本体（先核验定性）；不改翻译门/策略门实现。

## 验收一句话 [必填]
种"前端旁路门派发动钱/越权 tool_call" → 审计测试必抓；若现状已旁路，产出诚实 finding（🟡缺口）而非假绿灯。
