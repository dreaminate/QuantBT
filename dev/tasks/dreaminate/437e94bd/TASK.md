---
uuid: 437e94bd4e1e4a56bf2c52c6b96ed333
title: Agent Orchestrator——role agent 调度 + 23 事件投影 + Plan/ReAct/Review/Replay/Repair（A-AGENT-ORCH）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P0
area: agent-orchestrator
source: goal
source_ref: GOAL §7(Agent Shell→Orchestrator→LLM Gateway→role dispatch·12 role agent·23 可见事件·Plan/ReAct/Review/Replay/Repair·所有 role agent 受 deterministic DAG/governed compiler 管理·只经工具权限/canonical command/compiler 写 Research Graph)
depends_on: [640b66a0cfb44c3295b2fa8cf57a3568]
---

# Agent Orchestrator（A-AGENT-ORCH·LINE-A-AGENT 续·LLM Gateway 已解锁）

## Scope [必填·先读 GOAL §7]
LLM Gateway（640b66a0）已建唯一调用入口。本卡建 **Agent Orchestrator**——§7「Agent Shell→Agent Orchestrator→LLM Gateway→role agent dispatch」：① role agent 调度（12 role：Coordinator/Planner、Literature/Mathematical Researcher、Data/Factor/Model/Signal/StrategyBook/Backtest Engineer、Risk Analyst、Verifier/Critic、Reporter·串行/并行）② **23 可见事件投影**到 user 工作流（AgentPlanCreated/RoleAgentDispatched/LLMRouteSelected/…/RunVerdictProduced）③ Plan/ReAct/Review/Replay/Repair 五形态 ④ 所有 role agent 受 deterministic DAG 管理·只经工具权限/canonical command 写 Research Graph。**wrap 现有 agent_runtime.py 不重建**·LLM 调用全经 LLM Gateway（绕过→拒）。

## 领地（greenfield·只动·扩展不替换）
新 `app/backend/app/agent/orchestrator.py`（+ roles/ 若需·role dispatch + 23 事件 + 五形态 + DAG 管理）。**读/wrap**：agent_runtime.py（adapter·不改内部）、llm/gateway（唯一 LLM 入口·A-AGENT-GW 已建）、dag/kernel（deterministic DAG）、graph/research_graph、lineage/ids。**绝不碰** main.py、llm/ 内部、graph/qro 内部、其他在飞线。

## 可证伪验收（种坏门必抓·§7）
1. 多 Agent 绕过 DAG 自由派发工具 → 拒（对抗：构造绕 DAG 派发→必抓；MUT 放过→红）。
2. AgentLLMCall 绕过 LLM Gateway → 拒（所有 LLM 经 Gateway）。
3. Verifier 与 Builder 共用同一输出上下文且未标独立性不足 → 拒（§7·独立性写 LLMCallRecord）。
4. Agent 声称完成但工具记录缺失 → 拒；AgentPlan 缺 todo/dependencies/acceptance gates → 保持 draft；AgentCodeChange 缺 diff/test/rollback → 拒。
5. Agent 替 user 拍板方法学松紧 → 拒（§7·只记 MethodologyChoiceRecord 不替决）。

## 红线 [按需]
role agent 不直接调 provider/读 key（经 Gateway）·绕过 DAG/Gateway→拒·复用 ids.content_hash·扩展不替换(wrap agent_runtime 不改)·Agent 不替 user 拍方法学·先读 GOAL §7 再动手。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不建前端工作流可视化（23 事件后端投影即可）；不重建 LLM Gateway（已建·只调用）；record/replay store 深接线另卡。本卡只 Orchestrator 核+role dispatch+23 事件+五形态。
